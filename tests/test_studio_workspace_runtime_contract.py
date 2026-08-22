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
        raise AssertionError(
            "node is required to execute the workspace script and was not found on PATH."
        )
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
        result = subprocess.run(
            [node, str(path)], capture_output=True, text=True, timeout=120
        )
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
        self.assertEqual(
            got["loadErrors"],
            [],
            "the module threw while loading with no sidecar present",
        )

    def test_loads_without_throwing_with_a_sidecar(self) -> None:
        got = render(FAKE_SIDECAR, "return {};")
        self.assertEqual(
            got["loadErrors"],
            [],
            "the module threw while loading with a fake sidecar present",
        )


class DesktopOnlyDegradeIsHonest(unittest.TestCase):
    """Outside Electron, the workspace says so instead of rendering a dead ribbon."""

    def test_no_sidecar_shows_an_explicit_desktop_only_message(self) -> None:
        got = render(
            "",
            "const root = q('#studio-workspace');"
            "return { text: root.textContent, hasRibbon: !!q('.sw-ribbon-tab') };",
        )
        self.assertIn("Desktop only", got["text"])
        self.assertFalse(
            got["hasRibbon"],
            "no ribbon should render when there is no sidecar to drive it",
        )


class TheRibbonRendersAllSeventeenTabs(unittest.TestCase):
    def test_every_ribbon_tab_from_the_design_is_present(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "return { tabs: all('.sw-ribbon-tab').map(b => b.textContent) };",
        )
        expected = [
            "Home",
            "Selection",
            "Operations",
            "Structures",
            "Chunks",
            "Terrain",
            "Build",
            "Entities",
            "Data",
            "Analyze",
            "Redstone",
            "Worldgen",
            "View",
            "Panels",
            "Extend",
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
        self.assertTrue(
            got["disabled"],
            "Undo has no open world in this fixture and must stay disabled",
        )
        self.assertIn("Open a world", got["title"])

    def test_undo_is_wired_and_enabled_once_a_world_is_streaming(self) -> None:
        got = render(
            FAKE_SIDECAR + """
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
        self.assertFalse(
            got["wasDisabled"],
            "Undo must render enabled once __AmuletViewportPanel reports streaming",
        )
        self.assertTrue(
            got["called"], "clicking the wired Undo button must call the real runUndo()"
        )


class TheNavigatorReflectsSidecarDimensions(unittest.TestCase):
    def test_empty_state_before_any_world_is_open(self) -> None:
        got = render(FAKE_SIDECAR, "return { text: q('.sw-navigator').textContent };")
        self.assertIn("No world open yet", got["text"])

    def test_opening_a_world_populates_the_navigator_from_world_dimensions(
        self,
    ) -> None:
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

    def test_status_bar_and_viewport_host_ids_are_present_for_viewport_panel_js(
        self,
    ) -> None:
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
        self.assertTrue(
            all(
                [
                    got["status"],
                    got["host"],
                    got["canvas"],
                    got["empty"],
                    got["openRow"],
                    got["openButton"],
                    got["pathInput"],
                ]
            )
        )


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
        self.assertFalse(
            got["wasDisabled"],
            "Histogram must render enabled with a sidecar, a streaming world, and a selection",
        )
        self.assertIsNotNone(
            got["calledWith"],
            "clicking Histogram must call Site.electronSidecar.analyze.blockHistogram",
        )
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

    def test_analyze_without_a_selection_reports_an_honest_error_not_a_crash(
        self,
    ) -> None:
        got = render(
            FAKE_SIDECAR + """
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
        self.assertIsNotNone(
            got["errorRow"],
            "clicking Histogram with no selection must report an honest error, not silently do nothing",
        )

    def test_entity_counts_is_wired_like_the_other_analyze_commands(self) -> None:
        got = render(
            FAKE_SIDECAR
            + """
            window.AmuletSite = { electronSidecar: { analyze: {
              entityCounts: function (worldId, dimension, min, max) {
                window.__entityCountsCalledWith = Array.prototype.slice.call(arguments);
                return Promise.resolve({
                  entities_found: 2,
                  distinct_entity_types: 1,
                  entities: [{ entity: "minecraft:cow", count: 2 }],
                });
              },
            } } };
            window.__AmuletViewportPanel = { isStreaming: () => true,
              getWorldId: () => "fixture-world-id",
              getDimension: () => "minecraft:overworld",
              edit: { readPoints: () => ({ point1: [1, 2, 3], point2: [4, 5, 6] }) } };
            """,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Analyze').click();"
            "const counts = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Entity counts') !== -1);"
            "counts.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "const rows = [...all('.sw-pane-section-title'), ...all('.sw-pane-row-value')].map(e => e.textContent);"
            "return { disabled: counts.disabled, calledWith: window.__entityCountsCalledWith, rows };",
        )
        self.assertFalse(got["disabled"])
        self.assertEqual(
            got["calledWith"],
            ["fixture-world-id", "minecraft:overworld", [1, 2, 3], [4, 5, 6]],
        )
        self.assertIn("Entity counts", "".join(got["rows"]))
        self.assertIn("212", "".join(got["rows"]))


class TheTerrainEntitiesAndDataTabsCallTheRealBridge(unittest.TestCase):
    """Flatten/Sea level/Repaint/Cuboid/Entities/level.dat/Game rules must call
    Site.electronSidecar.terrain.*/entities.*/data.*, never a dead
    ``run: null`` -- and the commands amulet-core genuinely cannot perform
    (Raise, Noise, Sphere, Place, Remove, ...) must keep their honest
    disabled-with-reason state."""

    WORKSHOP_FIXTURE = """
    window.AmuletSite = { electronSidecar: {
      terrain: {
        flatten: function () {
          window.__terrainCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ blocks_changed: 12, height: 5 });
        },
        seaLevel: function () {
          window.__seaLevelCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ blocks_changed: 3, sea_level: 4, mode: "raise" });
        },
        repaint: function () {
          window.__repaintCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ blocks_changed: 1 });
        },
      },
      entities: {
        list: function () {
          window.__entitiesListCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ count: 1, entities: [{ namespace: "minecraft", base_name: "cow", x: 1, y: 2, z: 3 }] });
        },
        place: function () {
          window.__entitiesPlaceCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ placed: { namespace: "minecraft", base_name: "cow" } });
        },
        remove: function () {
          window.__entitiesRemoveCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ removed: 2 });
        },
      },
      data: {
        readLevel: function () {
          window.__levelReadCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ level_name: "Fixture World", data_version: 1, difficulty: 2, hardcore: false, raining: false, thundering: false });
        },
        writeLevel: function () {
          window.__levelWriteCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ updated: ["level_name"] });
        },
        readGameRules: function () {
          window.__gameRulesReadCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ game_rules: { doFire: "true" } });
        },
        writeGameRules: function () {
          window.__gameRulesWriteCalledWith = Array.prototype.slice.call(arguments);
          return Promise.resolve({ updated: ["doFire"] });
        },
      },
      confirmDestructive: function (opts) { opts.onConfirm(); },
    } };
    window.__AmuletViewportPanel = {
      isStreaming: () => true,
      getWorldId: () => "fixture-world-id",
      getDimension: () => "minecraft:overworld",
      edit: {
        readPoints: () => ({ point1: [0, 0, 0], point2: [3, 6, 3] }),
        blockValue: () => "universal_minecraft:stone",
        entityTypeValue: () => "minecraft:cow",
        seaLevelModeValue: () => "raise",
      },
      runPlaceEntity: function () {
        return window.AmuletSite.electronSidecar.entities.place(
          "fixture-world-id", "minecraft:overworld", [0, 0, 0], "minecraft", "cow", true
        );
      },
      runRemoveEntities: function () {
        return window.AmuletSite.electronSidecar.entities.remove(
          "fixture-world-id", "minecraft:overworld", [0, 0, 0], [3, 6, 3], "minecraft", "cow", true
        );
      },
      runWriteLevel: function () {
        return window.AmuletSite.electronSidecar.data.writeLevel(
          "fixture-world-id", { level_name: "New Name" }, true
        );
      },
      runWriteGameRules: function () {
        return window.AmuletSite.electronSidecar.data.writeGameRules(
          "fixture-world-id", { doFire: "false" }, true
        );
      },
    };
    """

    def test_flatten_is_enabled_and_calls_the_bridge(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Terrain').click();"
            "const flatten = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Flatten') !== -1);"
            "const wasDisabled = flatten.disabled;"
            "flatten.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "const section = [...all('.sw-pane-section-title')].map(e => e.textContent).join('|');"
            "return { wasDisabled, calledWith: window.__terrainCalledWith, section };",
        )
        self.assertFalse(got["wasDisabled"])
        self.assertIsNotNone(got["calledWith"])
        self.assertIn("Workshop", got["section"])

    def test_sea_level_and_repaint_are_also_wired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Terrain').click();"
            "const seaLevel = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Sea level') !== -1);"
            "const repaint = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Repaint') !== -1);"
            "seaLevel.click(); repaint.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "return { seaLevel: window.__seaLevelCalledWith, repaint: window.__repaintCalledWith };",
        )
        self.assertIsNotNone(got["seaLevel"])
        self.assertIsNotNone(got["repaint"])

    def test_cuboid_reuses_the_real_fill_write_path(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE + """
            window.__fillCalled = false;
            window.__AmuletViewportPanel.runFill = function () { window.__fillCalled = true; };
            """,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Build').click();"
            "const cuboid = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Cuboid') !== -1);"
            "const wasDisabled = cuboid.disabled;"
            "cuboid.click();"
            "return { wasDisabled, called: window.__fillCalled };",
        )
        self.assertFalse(got["wasDisabled"])
        self.assertTrue(
            got["called"],
            "Cuboid must call the real runFill(), the same write path as Operations > Fill",
        )

    def test_entities_list_is_wired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Entities').click();"
            "const entities = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Entities') !== -1);"
            "const wasDisabled = entities.disabled;"
            "entities.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "return { wasDisabled, calledWith: window.__entitiesListCalledWith };",
        )
        self.assertFalse(got["wasDisabled"])
        self.assertIsNotNone(got["calledWith"])

    def test_entities_place_and_remove_are_wired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Entities').click();"
            "const place = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Place') !== -1);"
            "const remove = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Remove') !== -1);"
            "const placeDisabled = place.disabled, removeDisabled = remove.disabled;"
            "place.click(); remove.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "return { placeDisabled, removeDisabled, placeCalled: window.__entitiesPlaceCalledWith, removeCalled: window.__entitiesRemoveCalledWith };",
        )
        self.assertFalse(got["placeDisabled"])
        self.assertFalse(got["removeDisabled"])
        self.assertIsNotNone(got["placeCalled"])
        self.assertIsNotNone(got["removeCalled"])

    def test_write_level_dat_and_write_game_rule_are_wired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Data').click();"
            "const writeLevel = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Write level.dat') !== -1);"
            "const writeRule = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Write game rule') !== -1);"
            "const writeLevelDisabled = writeLevel.disabled, writeRuleDisabled = writeRule.disabled;"
            "writeLevel.click(); writeRule.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "return { writeLevelDisabled, writeRuleDisabled, levelCalled: window.__levelWriteCalledWith, rulesCalled: window.__gameRulesWriteCalledWith };",
        )
        self.assertFalse(got["writeLevelDisabled"])
        self.assertFalse(got["writeRuleDisabled"])
        self.assertIsNotNone(got["levelCalled"])
        self.assertIsNotNone(got["rulesCalled"])

    def test_level_dat_and_game_rules_are_wired(self) -> None:
        got = render(
            FAKE_SIDECAR + self.WORKSHOP_FIXTURE,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Data').click();"
            "const level = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('level.dat') !== -1);"
            "const rules = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Game rules') !== -1);"
            "const levelDisabled = level.disabled, rulesDisabled = rules.disabled;"
            "level.click(); rules.click();"
            "await new Promise(r => setTimeout(r, 20));"
            "return { levelDisabled, rulesDisabled, levelCalled: window.__levelReadCalledWith, rulesCalled: window.__gameRulesReadCalledWith };",
        )
        self.assertFalse(got["levelDisabled"])
        self.assertFalse(got["rulesDisabled"])
        self.assertIsNotNone(got["levelCalled"])
        self.assertIsNotNone(got["rulesCalled"])


class TheViewTabTogglesRealLocalUiState(unittest.TestCase):
    """Layers/Navigator/Ribbon/Properties/Options are all local UI state or a
    real overlay call -- none needs the sidecar's write path, but Layers is
    gated on a streaming world (there is nothing to toggle a grid over
    before one exists), matching its own requiresWorld declaration."""

    def test_layers_toggles_the_real_grid_via_viewport_panel(self) -> None:
        got = render(
            FAKE_SIDECAR + """
            window.__gridVisible = true;
            window.__AmuletViewportPanel = {
              isStreaming: () => true,
              edit: { readPoints: () => null },
              isGridVisible: () => window.__gridVisible,
              setGridVisible: function (v) { window.__gridVisible = !!v; return window.__gridVisible; },
            };
            """,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'View').click();"
            "const layers = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Layers') !== -1);"
            "const wasDisabled = layers.disabled;"
            "layers.click();"
            "return { wasDisabled, afterClick: window.__gridVisible };",
        )
        self.assertFalse(
            got["wasDisabled"], "Layers must render enabled once a world is streaming"
        )
        self.assertFalse(
            got["afterClick"],
            "clicking Layers must call the real setGridVisible(), toggling it off",
        )

    def test_layers_is_disabled_without_a_streaming_world(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'View').click();"
            "const layers = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Layers') !== -1);"
            "return { disabled: layers.disabled, title: layers.title };",
        )
        self.assertTrue(got["disabled"])
        self.assertIn("Open a world", got["title"])

    def test_navigator_toggle_hides_and_reshows_the_real_navigator(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'View').click();"
            "const navBtn = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Navigator') !== -1);"
            "const before = q('.sw-navigator').hidden;"
            "navBtn.click();"
            "const afterFirstClick = q('.sw-navigator').hidden;"
            "navBtn.click();"
            "const afterSecondClick = q('.sw-navigator').hidden;"
            "return { before, afterFirstClick, afterSecondClick };",
        )
        self.assertFalse(got["before"])
        self.assertTrue(
            got["afterFirstClick"],
            "clicking Navigator once must hide the real navigator panel",
        )
        self.assertFalse(
            got["afterSecondClick"], "clicking Navigator again must show it again"
        )

    def test_options_opens_the_real_appearance_editor_when_available(self) -> None:
        got = render(
            FAKE_SIDECAR + """
            window.__appearanceMounted = false;
            window.AmuletStudioAppearance = { mount: function () { window.__appearanceMounted = true; } };
            """,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'View').click();"
            "const options = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Options') !== -1);"
            "const wasDisabled = options.disabled;"
            "options.click();"
            "return { wasDisabled, mounted: window.__appearanceMounted };",
        )
        self.assertFalse(
            got["wasDisabled"],
            "Options must render enabled once window.AmuletStudioAppearance exists",
        )
        self.assertTrue(
            got["mounted"],
            "clicking Options must mount the real appearance editor overlay",
        )

    def test_options_is_disabled_without_the_appearance_editor_module(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'View').click();"
            "const options = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Options') !== -1);"
            "return { disabled: options.disabled };",
        )
        self.assertTrue(got["disabled"])


class ThePanelsTabInspectorOpensTheRealPropertiesPane(unittest.TestCase):
    def test_inspector_reopens_and_focuses_the_properties_tab(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'View').click();"
            "const properties = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Properties') !== -1);"
            "properties.click();"
            "const closedAfterToggle = !q('.sw-pane .sw-pane-header');"
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Panels').click();"
            "const inspector = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Inspector') !== -1);"
            "const wasDisabled = inspector.disabled;"
            "inspector.click();"
            "const reopened = !!q('.sw-pane .sw-pane-header');"
            "const activeTab = all('.sw-pane-tab').find(t => t.getAttribute('aria-selected') === 'true');"
            "return { closedAfterToggle, wasDisabled, reopened, activeTabLabel: activeTab && activeTab.textContent };",
        )
        self.assertTrue(
            got["closedAfterToggle"], "test setup must actually close the pane first"
        )
        self.assertFalse(
            got["wasDisabled"], "Inspector is real local UI and must never be disabled"
        )
        self.assertTrue(
            got["reopened"], "clicking Inspector must reopen the real properties pane"
        )
        self.assertEqual(got["activeTabLabel"], "Properties")


class TheAutomateTabOpensTheRealNotificationDrawer(unittest.TestCase):
    def test_notifications_presses_the_real_notif_open_button(self) -> None:
        got = render(
            FAKE_SIDECAR + """
            window.__notifOpenClicked = false;
            """,
            "const notifOpen = window.document.createElement('button');"
            "notifOpen.id = 'notif-open';"
            "notifOpen.addEventListener('click', () => { window.__notifOpenClicked = true; });"
            "window.document.body.appendChild(notifOpen);"
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Automate').click();"
            "const notifications = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Notifications') !== -1);"
            "const wasDisabled = notifications.disabled;"
            "notifications.click();"
            "return { wasDisabled, clicked: window.__notifOpenClicked };",
        )
        self.assertFalse(
            got["wasDisabled"],
            "Notifications is real local UI (a button press) and must never be disabled",
        )
        self.assertTrue(
            got["clicked"],
            "clicking the ribbon's Notifications command must press the real #notif-open button",
        )

    def test_release_notes_and_memory_console_are_still_honestly_unwired(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "all('.sw-ribbon-tab').find(b => b.textContent === 'Automate').click();"
            "const releaseNotes = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Release notes') !== -1);"
            "const memoryConsole = all('.sw-ribbon-btn').find(b => b.textContent.indexOf('Memory console') !== -1);"
            "return { releaseNotesDisabled: releaseNotes.disabled, memoryConsoleDisabled: memoryConsole.disabled };",
        )
        self.assertTrue(got["releaseNotesDisabled"])
        self.assertTrue(got["memoryConsoleDisabled"])


if __name__ == "__main__":
    unittest.main()
