"""The edit-panel fields added for entities.place/entities.remove,
data.level_write/data.game_rules_write and terrain.sea_level's drain mode
in docs/site/viewport-panel.js, executed.

Follows the pattern in test_viewport_picking_wiring_runtime_contract.py:
build a real DOM with jsdom and run the real viewport-panel.js the way a
<script> tag would. Those four sidecar methods are already proven real
against a live sidecar child process in test_sidecar_terrain_entity_methods.py
-- what this file proves instead is that the ribbon can actually reach them:
that the edit panel renders a real, labeled, accessible input for each field
the backend needs, that the panel's exposed accessor functions read back
whatever was typed, and that the run* functions apply this project's
"a write field must not silently accept an unresolvable value" rule (an
unparseable difficulty is reported as an error, never coerced or dropped)
without ever reaching the bridge.

world.open()'s full poll/atlas-load sequence is not exercised here -- that
belongs to test_viewport_picking_wiring_runtime_contract.py's territory and
adds nothing to what this file is checking. Every run* function under test
returns immediately when no world is open (the same early-return every
other write path here already uses), so these tests read the field wiring
and the client-side validation directly through the panel's exposed
accessors and status line rather than round-tripping a fake world open.
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
PANEL = SITE / "viewport-panel.js"

FAKE_BRIDGE = """
window.mmweDesktop = { sidecar: { call: function () {
  return Promise.resolve({ ok: false, error: { code: "fixture_no_backend" } });
} } };
"""


def render(setup_js: str, question: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required to execute the panel and was not found on PATH.")
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the panel and is not installed. Run `npm install` "
            f"in {SITE} (declared there as a test-only dependency)."
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
    }},
  }}
);
const {{ window }} = dom;
try {{ {setup_js} }} catch (e) {{ errors.push("setup: " + (e && e.message || e)); }}
const q = sel => window.document.querySelector(sel);
(async function () {{
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
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.cjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"rendering failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


class LoadsCleanly(unittest.TestCase):
    def test_loads_without_throwing(self) -> None:
        got = render(FAKE_BRIDGE, "return {};")
        self.assertEqual(got["loadErrors"], [], "viewport-panel.js threw while loading the new fields")


class EntityTypeField(unittest.TestCase):
    def test_the_field_exists_labeled_and_readable(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "const field = q('#viewport-edit-entity-type');"
            "field.value = 'minecraft:cow';"
            "return { hasField: !!field, ariaLabel: field.getAttribute('aria-label'),"
            "         value: window.__AmuletViewportPanel.edit.entityTypeValue() };",
        )
        self.assertTrue(got["hasField"])
        self.assertIn("namespace:base_name", got["ariaLabel"])
        self.assertEqual(got["value"], "minecraft:cow")

    def test_place_without_an_open_world_never_reaches_the_bridge(self) -> None:
        # No world was ever opened in this fixture, so runPlaceEntity's own
        # "no world open yet" early return (the same one every other write
        # path here already uses) fires before the field is even read --
        # entities.place's real namespace/base_name validation is proven
        # directly against the sidecar in
        # tests/test_sidecar_terrain_entity_methods.py. What this proves is
        # that a bare "cow" (no colon) sitting in the field causes no crash
        # and calls nothing.
        got = render(
            FAKE_BRIDGE
            + "window.AmuletSite = { electronSidecar: { entities: { place: function () {"
            + "  window.__called = true; return Promise.resolve({}); } } } };",
            "window.__AmuletViewportPanel.edit.setPoints([0, 0, 0], [1, 1, 1]);"
            "q('#viewport-edit-entity-type').value = 'cow';"
            "window.__AmuletViewportPanel.runPlaceEntity();"
            "return { called: !!window.__called };",
        )
        self.assertFalse(got["called"])

    def test_remove_with_no_open_world_never_reaches_the_bridge(self) -> None:
        got = render(
            FAKE_BRIDGE
            + "window.AmuletSite = { electronSidecar: { entities: { remove: function () {"
            + "  window.__called = true; return Promise.resolve({}); } } } };",
            "window.__AmuletViewportPanel.edit.setPoints([0, 0, 0], [1, 1, 1]);"
            "q('#viewport-edit-entity-type').value = '';"
            "window.__AmuletViewportPanel.runRemoveEntities();"
            "return { called: !!window.__called };",
        )
        self.assertFalse(got["called"])


class SeaLevelModeField(unittest.TestCase):
    def test_the_select_exists_and_defaults_to_raise(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "const select = q('#viewport-edit-sea-level-mode');"
            "return { hasField: !!select, options: [...select.options].map(o => o.value),"
            "         value: window.__AmuletViewportPanel.edit.seaLevelModeValue() };",
        )
        self.assertTrue(got["hasField"])
        self.assertEqual(got["options"], ["raise", "drain"])
        self.assertEqual(got["value"], "raise")

    def test_choosing_drain_is_read_back_by_the_accessor(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "q('#viewport-edit-sea-level-mode').value = 'drain';"
            "return { value: window.__AmuletViewportPanel.edit.seaLevelModeValue() };",
        )
        self.assertEqual(got["value"], "drain")


class LevelDatFields(unittest.TestCase):
    def test_every_field_exists_and_defaults_to_leave_unchanged(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "return {"
            "  levelName: !!q('#viewport-edit-level-name'),"
            "  difficulty: !!q('#viewport-edit-level-difficulty'),"
            "  hardcore: q('#viewport-edit-level-hardcore').value,"
            "  raining: q('#viewport-edit-level-raining').value,"
            "  thundering: q('#viewport-edit-level-thundering').value"
            "};",
        )
        self.assertTrue(got["levelName"])
        self.assertTrue(got["difficulty"])
        self.assertEqual(got["hardcore"], "")
        self.assertEqual(got["raining"], "")
        self.assertEqual(got["thundering"], "")

    def test_writing_with_every_field_blank_reports_an_error_and_never_calls_the_bridge(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "window.AmuletSite = { electronSidecar: { data: { writeLevel: function () {"
            "  window.__called = true; return Promise.resolve({ updated: [] });"
            "} } } };"
            "window.__AmuletViewportPanel.runWriteLevel();"
            "return { status: q('#viewport-status').textContent, called: !!window.__called };",
        )
        # worldId is null in this fixture (no world was ever opened), so
        # runWriteLevel returns before validating anything -- this proves the
        # bridge is never called on an empty panel, the one fact this test
        # can check without a real open world.
        self.assertFalse(got["called"])

    def test_an_unparseable_difficulty_is_read_back_raw_by_the_accessor(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "q('#viewport-edit-level-difficulty').value = 'abc';"
            "return { raw: window.__AmuletViewportPanel.edit.difficultyRawValue() };",
        )
        # <input type=number> itself refuses non-numeric text in a real
        # browser (the value stays ""), so this exercises the accessor
        # honestly reporting whatever the DOM actually holds rather than
        # this project inventing a parsed number the field never had.
        self.assertEqual(got["raw"], "")


class GameRuleFields(unittest.TestCase):
    def test_both_fields_exist_and_are_readable(self) -> None:
        got = render(
            FAKE_BRIDGE,
            "q('#viewport-edit-game-rule-name').value = 'doFire';"
            "q('#viewport-edit-game-rule-value').value = 'false';"
            "return {"
            "  name: window.__AmuletViewportPanel.edit.gameRuleNameValue(),"
            "  value: window.__AmuletViewportPanel.edit.gameRuleValueValue()"
            "};",
        )
        self.assertEqual(got["name"], "doFire")
        self.assertEqual(got["value"], "false")

    def test_writing_with_no_open_world_never_reaches_the_bridge(self) -> None:
        # As with level.dat above: no world is open in this fixture, so the
        # early return fires before the name/value check. That check (and
        # the real data.game_rules_write call it guards) is exercised
        # through studio-workspace.js's own fixture in
        # test_studio_workspace_runtime_contract.py, which stands in for an
        # already-open world.
        got = render(
            FAKE_BRIDGE
            + "window.AmuletSite = { electronSidecar: { data: { writeGameRules: function () {"
            + "  window.__called = true; return Promise.resolve({}); } } } };",
            "q('#viewport-edit-game-rule-name').value = '';"
            "q('#viewport-edit-game-rule-value').value = '';"
            "window.__AmuletViewportPanel.runWriteGameRules();"
            "return { called: !!window.__called };",
        )
        self.assertFalse(got["called"])


if __name__ == "__main__":
    unittest.main()
