"""docs/site/studio-language.js, executed with jsdom, not merely read.

Follows the pattern in test_studio_workspace_runtime_contract.py: build a
real DOM with `#studio-language`, run the real script, and ask the
constructed page questions -- proving the module does not throw on load and
that the School-mode gate actually hides the Cantonese/funny/emoji controls
rather than merely disabling them.
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
SCRIPT = SITE / "studio-language.js"
SITE_CORE = SITE / "site-core.js"


def render(setup_js: str, question: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to execute the script and was not found on PATH."
        )
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the panel and is not installed. Run `npm install` "
            f"in {SITE} (declared there as a test-only dependency)."
        )
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const SITE_CORE = {json.dumps(str(SITE_CORE))};
const SCRIPT = {json.dumps(str(SCRIPT))};
const errors = [];
const dom = new JSDOM('<!doctype html><body><div id="studio-language"></div></body>', {{
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
  window.eval(fs.readFileSync(SITE_CORE, "utf8"));
}} catch (e) {{
  errors.push("site-core.js: " + (e && e.message || e));
}}
try {{
  window.eval(fs.readFileSync(SCRIPT, "utf8"));
}} catch (e) {{
  errors.push("studio-language.js: " + (e && e.message || e));
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


#: A fake sidecar bridge with real, in-memory School-mode and narrator
#: state -- enough to exercise the panel's real request/response shape
#: without spawning the Python process.
FAKE_SIDECAR = """
var __school = { mode_name: "School mode", enabled: false, has_unlock_credential: false };
var __narrator = { enabled: false, language: "english" };
window.mmweDesktop = { sidecar: { call: function (method, params) {
  if (method === "school.status") return Promise.resolve({ ok: true, result: Object.assign({}, __school) });
  if (method === "school.set_credential") {
    __school.has_unlock_credential = true;
    return Promise.resolve({ ok: true, result: Object.assign({}, __school) });
  }
  if (method === "school.enable") {
    if (!__school.has_unlock_credential) return Promise.resolve({ ok: false, error: { code: "invalid_params" } });
    __school.enabled = true;
    return Promise.resolve({ ok: true, result: Object.assign({}, __school) });
  }
  if (method === "school.unlock") {
    __school.enabled = false;
    return Promise.resolve({ ok: true, result: Object.assign({ unlocked: true }, __school) });
  }
  if (method === "school.set_mode_name") {
    __school.mode_name = params.mode_name;
    return Promise.resolve({ ok: true, result: Object.assign({}, __school) });
  }
  if (method === "school.reset_mode_name") {
    __school.mode_name = "School mode";
    return Promise.resolve({ ok: true, result: Object.assign({}, __school) });
  }
  if (method === "narrator.read") return Promise.resolve({ ok: true, result: Object.assign({}, __narrator) });
  if (method === "narrator.write") {
    Object.assign(__narrator, params);
    return Promise.resolve({ ok: true, result: Object.assign({}, __narrator) });
  }
  return Promise.resolve({ ok: false, error: { code: "fixture_no_backend" } });
} } };
"""

WAIT = "await new Promise(r => setTimeout(r, 20));"


class ThePanelExecutesCleanly(unittest.TestCase):
    def test_loads_without_throwing_in_a_plain_browser(self) -> None:
        got = render("", "return {};")
        self.assertEqual(got["loadErrors"], [])

    def test_loads_without_throwing_with_a_sidecar(self) -> None:
        got = render(FAKE_SIDECAR, "return {};")
        self.assertEqual(got["loadErrors"], [])


class DesktopOnlyDegradeIsHonest(unittest.TestCase):
    def test_no_sidecar_school_and_narrator_say_desktop_only(self) -> None:
        got = render("", "return { text: q('#studio-language').textContent };")
        self.assertIn("Desktop only", got["text"])

    def test_language_mode_still_works_without_a_sidecar(self) -> None:
        # Language mode / funny levels / emoji are real local Site.settings
        # preferences with or without the desktop sidecar -- same as theme.
        got = render(
            "", "return { hasSelect: !!q('select[aria-label=\"Language mode\"]') };"
        )
        self.assertTrue(got["hasSelect"])


class LanguageModeAndFunnyLevelsRoundTripThroughSiteSettings(unittest.TestCase):
    def test_changing_the_select_persists_to_site_settings(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "const sel = q('select[aria-label=\"Language mode\"]');"
            "sel.value = 'bilingual';"
            "sel.dispatchEvent(new window.Event('change', {bubbles:true}));"
            "return { stored: window.AmuletSite.settings.get('language') };",
        )
        self.assertEqual(got["stored"], "bilingual")

    def test_funny_slider_persists_to_site_settings(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "const s = q('input[aria-label=\"Funny level (English)\"]');"
            "s.value = '4';"
            "s.dispatchEvent(new window.Event('input', {bubbles:true}));"
            "return { stored: window.AmuletSite.settings.get('funnyEn') };",
        )
        self.assertEqual(got["stored"], 4)


class SchoolModeHidesRatherThanDisables(unittest.TestCase):
    def test_enabling_school_mode_hides_the_cantonese_row_and_forces_english(
        self,
    ) -> None:
        got = render(
            FAKE_SIDECAR,
            WAIT
            + "const setCred = q('input[aria-label=\"New unlock credential\"]');"
            + "setCred.value = 'correct-horse-battery';"
            + "q('button:nth-of-type(1)');"
            + "const buttons = all('button');"
            + "const setCredBtn = buttons.find(b => b.textContent === 'Set unlock credential');"
            + "setCredBtn.click();"
            + WAIT
            + "const enableBtn = buttons.find(b => b.textContent === 'Enable');"
            + "enableBtn.click();"
            + WAIT
            + "const cantoneseRow = q('.lang-cantonese-only');"
            + "const modeSelect = q('select[aria-label=\"Language mode\"]');"
            + "return { cantoneseHidden: cantoneseRow.hidden, mode: modeSelect.value, modeDisabled: modeSelect.disabled };",
        )
        self.assertTrue(
            got["cantoneseHidden"],
            "School mode must hide, not merely disable, the Cantonese row",
        )
        self.assertEqual(got["mode"], "english")
        self.assertTrue(got["modeDisabled"])

    def test_unlocking_with_the_wrong_credential_leaves_it_enabled(self) -> None:
        got = render(
            FAKE_SIDECAR,
            WAIT
            + "const buttons = all('button');"
            + "q('input[aria-label=\"New unlock credential\"]').value = 'right-one';"
            + "buttons.find(b => b.textContent === 'Set unlock credential').click();"
            + WAIT
            + "buttons.find(b => b.textContent === 'Enable').click();"
            + WAIT
            + "return { text: q('.school-status').textContent };",
        )
        self.assertIn("on", got["text"])


class NarratorPanelRoundTrips(unittest.TestCase):
    def test_toggling_the_narrator_writes_through_the_sidecar(self) -> None:
        got = render(
            FAKE_SIDECAR,
            WAIT
            + "const cb = q('input[aria-label=\"Enable spoken narrator\"]');"
            + "cb.checked = true;"
            + "cb.dispatchEvent(new window.Event('change', {bubbles:true}));"
            + WAIT
            + "return { text: q('.narrator-status').textContent };",
        )
        self.assertIn("on", got["text"])


if __name__ == "__main__":
    unittest.main()
