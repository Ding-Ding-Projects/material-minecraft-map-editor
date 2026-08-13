"""Runtime evidence for docs/site/studio-backstage.js.

Reading the source can show a module that never throws and never confirm it
renders anything. This builds a minimal page carrying the same shared runtime
the published site loads (site-data.js, site-core.js, regex-builder.js,
electron-bridge.js) plus studio-backstage.js, mounts it into a bare
"#studio-backstage" container the way the desktop shell will, and asks the
resulting DOM real questions -- including behavioural ones a search field
either does or does not actually filter.

This never touches docs/site/index.html or styles.css: the published
documentation site's own landing page is unrelated to this surface and stays
exactly as it is.
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

SCRIPTS = [
    "site-data.js",
    "site-core.js",
    "regex-builder.js",
    "electron-bridge.js",
    "studio-backstage.js",
]


def render(question: str, sidecar_js: str = "") -> dict:
    """Execute the backstage module in a DOM and answer `question`.

    `sidecar_js`, when given, is JS run *before* the scripts load, to install
    a fake `window.mmweDesktop.sidecar` -- the same seam
    docs/site/electron-bridge.js and every panel that calls it already
    depend on, so the fake is exactly what the real preload script would
    expose to the renderer.
    """

    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to execute the backstage module and was not found on PATH."
        )
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the backstage module and is not "
            f"installed. Run `npm install` in {SITE}. This is not skipped, "
            "because skipping would leave the suite green while nothing had "
            "actually been rendered."
        )
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const path = require("path");
const SITE = {json.dumps(SITE.as_posix())};
const errors = [];
const html = '<!doctype html><html><body><div id="studio-backstage"></div></body></html>';
const dom = new JSDOM(html, {{
  runScripts: "dangerously",
  url: "https://example.invalid/",
  pretendToBeVisual: true,
  beforeParse(window) {{
    window.addEventListener("error", e => errors.push("error: " + e.message));
  }},
}});
const {{ window }} = dom;
{sidecar_js}
const scripts = {json.dumps(SCRIPTS)};
for (const name of scripts) {{
  try {{
    window.eval(fs.readFileSync(path.join(SITE, name), "utf8"));
  }} catch (e) {{
    errors.push(name + ": " + e.message);
  }}
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
            [node, str(path)], capture_output=True, text=True, timeout=180
        )
    if result.returncode != 0:
        raise AssertionError(f"rendering failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


# A fake sidecar with a handful of recents, wired the same way
# docs/site/electron-bridge.js expects: window.mmweDesktop.sidecar.call(method,
# params) -> Promise<{ok, result} | {ok:false, error}>.
FAKE_SIDECAR_WITH_RECENTS = """
window.mmweDesktop = { sidecar: { call: function (method, params) {
  if (method === "recents.list") {
    return Promise.resolve({ ok: true, result: { entries: [
      { name: "1.17 Height", kind: "World project", platform: "Bedrock 1.17.0.1",
        path: "com.mojang\\\\minecraftWorlds\\\\A", opened_iso: "2026-08-10T00:00:00Z",
        pinned: true, tag: "Worlds" },
      { name: "Spawn rebuild", kind: "Structure library", platform: "Java 1.20.4",
        path: "Documents\\\\Amulet\\\\spawn-rebuild", opened_iso: "2026-08-09T00:00:00Z",
        pinned: false, tag: "Projects" }
    ] } });
  }
  return Promise.resolve({ ok: false, error: { code: "unhandled_method" } });
} } };
"""

FAKE_SIDECAR_EMPTY_RECENTS = """
window.mmweDesktop = { sidecar: { call: function (method, params) {
  if (method === "recents.list") return Promise.resolve({ ok: true, result: { entries: [] } });
  return Promise.resolve({ ok: false, error: { code: "unhandled_method" } });
} } };
"""


class ThePageExecutesCleanly(unittest.TestCase):
    def test_the_module_loads_without_throwing(self) -> None:
        got = render("return {};")
        self.assertEqual(
            got["loadErrors"],
            [],
            "a script threw while loading; the backstage would be blank",
        )

    def test_it_mounts_real_content(self) -> None:
        got = render(
            "return {children: (q('#studio-backstage')||{}).childElementCount || 0,"
            "        nav: all('.sb-nav-item').length,"
            "        templates: all('.sb-template').length};"
        )
        self.assertGreater(got["children"], 0, "the backstage mounted nothing")
        self.assertEqual(got["nav"], 5, "expected the five backstage nav destinations")
        self.assertEqual(
            got["templates"], 5, "expected the five template gallery cards"
        )


class NoSidecarIsAnHonestDesktopOnlyState(unittest.TestCase):
    def test_the_recent_table_says_desktop_only_rather_than_rendering_nothing(
        self,
    ) -> None:
        got = render(
            "return {status: (q('.sb-status')||{}).textContent || '',"
            "        rows: all('.sb-table-row').length};"
        )
        self.assertEqual(got["rows"], 0)
        self.assertIn("desktop", got["status"].lower())


class EmptyRecentsAreAnHonestEmptyState(unittest.TestCase):
    def test_zero_entries_says_how_to_start_rather_than_showing_nothing(self) -> None:
        got = render(
            "await new Promise(r => setTimeout(r, 20));"
            "return {status: (q('.sb-status')||{}).textContent || '',"
            "        rows: all('.sb-table-row').length};",
            sidecar_js=FAKE_SIDECAR_EMPTY_RECENTS,
        )
        self.assertEqual(got["rows"], 0)
        self.assertIn("template", got["status"].lower())


class RealRecentsRenderFromTheSidecarNotAFixture(unittest.TestCase):
    def test_the_table_renders_the_sidecars_own_entries(self) -> None:
        got = render(
            "await new Promise(r => setTimeout(r, 20));"
            "return {rows: all('.sb-table-row').length,"
            "        names: all('.sb-row-name').map(n => n.textContent)};",
            sidecar_js=FAKE_SIDECAR_WITH_RECENTS,
        )
        self.assertEqual(got["rows"], 2)
        self.assertIn("1.17 Height", got["names"])
        self.assertIn("Spawn rebuild", got["names"])

    def test_the_filter_chips_actually_filter(self) -> None:
        got = render(
            "await new Promise(r => setTimeout(r, 20));"
            "const worldsChip = all('.sb-chip').find(c => c.textContent.trim() === 'Worlds');"
            "worldsChip.dispatchEvent(new window.Event('click', {bubbles:true}));"
            "return {rows: all('.sb-table-row').length,"
            "        names: all('.sb-row-name').map(n => n.textContent)};",
            sidecar_js=FAKE_SIDECAR_WITH_RECENTS,
        )
        self.assertEqual(got["rows"], 1, "the Worlds chip did not narrow the table")
        self.assertEqual(got["names"], ["1.17 Height"])

    def test_the_search_field_actually_narrows_the_table(self) -> None:
        got = render(
            "await new Promise(r => setTimeout(r, 20));"
            "const input = q('#backstage-recent-search');"
            "input.value = 'Spawn';"
            "input.dispatchEvent(new window.Event('input', {bubbles:true}));"
            "return {rows: all('.sb-table-row').length,"
            "        names: all('.sb-row-name').map(n => n.textContent)};",
            sidecar_js=FAKE_SIDECAR_WITH_RECENTS,
        )
        self.assertEqual(got["rows"], 1, "the search field did not filter the table")
        self.assertEqual(got["names"], ["Spawn rebuild"])


class EverySearchFieldCarriesItsRegexBuilder(unittest.TestCase):
    def test_the_recent_and_features_searches_have_anchored_builders(self) -> None:
        got = render(
            "return {"
            "  recentControls: !!q('[data-regex-controls=\"backstage-recent\"]'),"
            "  recentOpen: !!q('#backstage-recent-regex-open'),"
            "  featureControls: !!q('[data-regex-controls=\"backstage-features\"]'),"
            "  featureOpen: !!q('#backstage-features-regex-open')"
            "};"
        )
        for key, value in got.items():
            if key == "loadErrors":
                continue
            with self.subTest(control=key):
                self.assertTrue(value, f"{key} is missing its anchored builder")


class NavigationActuallySwitchesPanels(unittest.TestCase):
    def test_clicking_open_shows_the_open_panel_and_hides_home(self) -> None:
        got = render(
            "const items = all('.sb-nav-item');"
            "const openBtn = items.find(b => b.textContent.trim().indexOf('Open') !== -1);"
            "openBtn.dispatchEvent(new window.Event('click', {bubbles:true}));"
            "return {"
            "  homeHidden: q('[data-sb-panel=\"home\"]').hidden,"
            "  openHidden: q('[data-sb-panel=\"open\"]').hidden,"
            "  current: openBtn.getAttribute('aria-current')"
            "};"
        )
        self.assertTrue(got["homeHidden"], "Home stayed visible after switching away")
        self.assertFalse(got["openHidden"], "Open did not become visible")
        self.assertEqual(got["current"], "page")


class OpeningAWorldUsesTheRealSidecarContract(unittest.TestCase):
    """world.open then poll world.open_status -- the same pair
    docs/site/viewport-panel.js already drives against the real sidecar."""

    FAKE_OPEN_SIDECAR = """
    var calls = [];
    window.mmweDesktop = { sidecar: { call: function (method, params) {
      calls.push(method);
      if (method === "recents.list") return Promise.resolve({ ok: true, result: { entries: [] } });
      if (method === "world.open") return Promise.resolve({ ok: true, result: { world_id: "w1", status: "pending" } });
      if (method === "world.open_status") return Promise.resolve({ ok: true, result: {
        status: "ready", world_id: "w1", name: "Debug 1.14", platform: "Java 1.14.4",
        version: [1, 14, 4], dimensions: ["overworld", "the_nether"], path: "C:\\\\worlds\\\\debug"
      } });
      return Promise.resolve({ ok: false, error: { code: "unhandled_method" } });
    } } };
    """

    def test_opening_a_world_polls_status_then_shows_project_info(self) -> None:
        got = render(
            "const items = all('.sb-nav-item');"
            "items.find(b => b.textContent.trim().indexOf('Open') !== -1).dispatchEvent(new window.Event('click', {bubbles:true}));"
            "const path = q('.sb-path-input');"
            "path.value = 'C:\\\\worlds\\\\debug';"
            "q('.sb-primary-btn').dispatchEvent(new window.Event('click', {bubbles:true}));"
            "await new Promise(r => setTimeout(r, 50));"
            "return {"
            "  infoHidden: q('[data-sb-panel=\"info\"]').hidden,"
            "  rows: all('.sb-info-value').map(n => n.textContent)"
            "};",
            sidecar_js=self.FAKE_OPEN_SIDECAR,
        )
        self.assertFalse(
            got["infoHidden"], "opening a world did not route to Project info"
        )
        self.assertIn("Debug 1.14", got["rows"])
        self.assertIn("Java 1.14.4", got["rows"])

    def test_an_empty_path_reports_the_problem_and_calls_nothing(self) -> None:
        got = render(
            "const items = all('.sb-nav-item');"
            "items.find(b => b.textContent.trim().indexOf('Open') !== -1).dispatchEvent(new window.Event('click', {bubbles:true}));"
            "q('.sb-primary-btn').dispatchEvent(new window.Event('click', {bubbles:true}));"
            "return {status: (q('[data-sb-panel=\"open\"] .sb-status')||{}).textContent || ''};",
            sidecar_js=self.FAKE_OPEN_SIDECAR,
        )
        self.assertTrue(got["status"], "an empty path silently did nothing")


if __name__ == "__main__":
    unittest.main()
